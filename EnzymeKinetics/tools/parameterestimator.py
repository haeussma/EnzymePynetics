from typing import List, Dict, Optional

from EnzymeKinetics.core.enzymekineticsexperiment import EnzymeKineticsExperiment
from EnzymeKinetics.core.stoichiometrytypes import StoichiometryTypes
from kineticmodel import KineticModel, irreversible_model, competitive_product_inhibition_model, uncompetitive_product_inhibition_model, noncompetitive_product_inhibition_model, substrate_inhibition_model, competitive_inhibition_model, uncompetitive_inhibition_model, noncompetitive_inhibition_model, partially_competitive_inhibition_model

import numpy as np
from pandas import DataFrame
from scipy.integrate import odeint
from lmfit import minimize, report_fit
from IPython.display import display
from matplotlib.cm import get_cmap
import matplotlib.pyplot as plt


class ParameterEstimator():

    def __init__(self, data: EnzymeKineticsExperiment):
        self.data = data
        self.models: Dict[str, KineticModel] = None
        self._initialize_measurement_data()
        self._check_negative_concentrations()
        self.initial_kcat = self._calculate_kcat()
        self.initial_Km = self._calculate_Km()
        # TODO shapcheck funtion to check for consistent array lengths

    def _initialize_measurement_data(self):

        measurement_data = []
        initial_substrate = []
        enzyme = []
        inhibitor = []

        for measurement in self.data.measurements:
            for replica in measurement.data:
                measurement_data.append(replica.values)
                initial_substrate.append(measurement.initial_substrate_conc)
                enzyme.append(measurement.enzyme_conc)
                if measurement.inhibitor_conc != None:
                    inhibitor.append(measurement.inhibitor_conc)
                else:
                    inhibitor.append(0)

        measurement_shape = np.array(measurement_data).shape

        self.time = np.array(self.data.time)
        self.initial_substrate = np.array(initial_substrate)
        self.enzyme = np.array(enzyme)
        self.inhibitor = np.repeat(np.array(inhibitor),measurement_shape[1]).reshape(measurement_shape)

        if self.data.stoichiometry == StoichiometryTypes.SUBSTRATE.value:
            self.substrate = np.array(measurement_data)
            self.product = np.array(self._calculate_product())
        elif self.data.stoichiometry == StoichiometryTypes.PRODUCT.value: 
            self.product = np.array(measurement_data)
            self.substrate = np.array(self._calculate_substrate())
        else:
            raise AttributeError("Please define whether measured data is substrate or product data.")

    def _calculate_substrate(self):
        substrate = []
        for product, initial_substrate in zip(self.product, self.initial_substrate):
            substrate.append(
                [initial_substrate - value for value in product])
        return substrate

    def _calculate_product(self):
        product = []
        for substrate, initial_substrate in zip(self.substrate, self.initial_substrate):
            product.append(
                [initial_substrate - value for value in substrate])
        return product

    def _calculate_rates(self):
        concentration_intervals = np.diff(self.substrate)
        time_intervals = np.diff(self.data.time)
        rates = abs(concentration_intervals / time_intervals)
        return rates

    def _calculate_kcat(self) -> float:
        rates = self._calculate_rates()
        initial_enzyme_tile = np.repeat(self.enzyme, rates.shape[1]).reshape(rates.shape)
        kcat = np.nanmax(rates / initial_enzyme_tile)
        return kcat

    def _calculate_Km(self):
        return np.nanmax(self._calculate_rates()) / 2

    def _check_negative_concentrations(self):
        if np.any(self.substrate<0):
            raise ValueError(
                "Substrate data contains negative concentrations. Check data.")        
        if np.any(self.product<0):
            raise ValueError(
                "Product data contains negative concentrations. Check data.")

    def _subset_data(self, initial_substrates: list = None, start_time_index: int = None, stop_time_index: int = None) -> tuple:
        idx = np.array([])
        if initial_substrates == None or len(initial_substrates) == 0:
            idx = np.arange(self.substrate.shape[0])
        else:
            for concentration in initial_substrates:
                if concentration not in self.initial_substrate:
                    raise ValueError(
                        f"{concentration} not found in initial substrate concentrations. \nInitial substrate concentrations are {list(np.unique(self.initial_substrate))}")
                else:
                    idx = np.append(idx, np.where(self.initial_substrate == concentration)[0])
        idx = idx.astype(int)

        new_substrate = self.substrate[idx,start_time_index:stop_time_index]
        new_product = self.product[idx,start_time_index:stop_time_index]
        new_enzyme = self.enzyme[idx]
        new_initial_substrate = self.initial_substrate[idx]
        new_time = self.time[start_time_index:stop_time_index]
        new_inhibitor = self.inhibitor[idx]

        return (new_substrate, new_product, new_enzyme, new_initial_substrate, new_time, new_inhibitor)


    def _initialize_models(self, substrate, product, enzyme, inhibitor) -> Dict[str, KineticModel]:

        if np.all(self.inhibitor == 0):

            irreversible_Michaelis_Menten = KineticModel(
                name="irreversible Michaelis Menten",
                params=[],
                w0={"cS": substrate, "cE": enzyme,
                    "cP": product, "cI": inhibitor},            
                kcat_initial=self.initial_kcat,
                Km_initial=self.initial_Km,
                model=irreversible_model,
                enzyme_inactivation=self.enzyme_inactivation
            )

            competitive_product_inhibition = KineticModel(
                name="competitive product inhibition",
                params=["K_ic"],
                w0={"cS": substrate, "cE": enzyme,
                    "cP": product, "cI": product},            
                kcat_initial=self.initial_kcat,
                Km_initial=self.initial_Km,
                model=competitive_product_inhibition_model,
                enzyme_inactivation=self.enzyme_inactivation
            )
            uncompetitive_product_inhibition = KineticModel(
                name="uncompetitive product inhibition",
                params=["K_iu"],
                w0={"cS": substrate, "cE": enzyme,
                    "cP": product, "cI": product},            
                kcat_initial=self.initial_kcat,
                Km_initial=self.initial_Km,
                model=uncompetitive_product_inhibition_model,
                enzyme_inactivation=self.enzyme_inactivation
            )
            noncompetitive_product_inhibition = KineticModel(
                name="non-competitive product inhibition",
                params=["K_iu", "K_ic"],
                w0={"cS": substrate, "cE": enzyme,
                    "cP": product, "cI": product},            
                kcat_initial=self.initial_kcat,
                Km_initial=self.initial_Km,
                model=noncompetitive_product_inhibition_model,
                enzyme_inactivation=self.enzyme_inactivation
            )
            substrate_inhibition = KineticModel(
                name="substrate inhibition",
                params=["K_iu"],
                w0={"cS": substrate, "cE": enzyme,
                    "cP": product, "cI": substrate},            
                kcat_initial=self.initial_kcat,
                Km_initial=self.initial_Km,
                model=substrate_inhibition_model,
                enzyme_inactivation=self.enzyme_inactivation
            )

            return {
                irreversible_Michaelis_Menten.name: irreversible_Michaelis_Menten,
                competitive_product_inhibition.name: competitive_product_inhibition,
                uncompetitive_product_inhibition.name: uncompetitive_product_inhibition,
                noncompetitive_product_inhibition.name: noncompetitive_product_inhibition,
                substrate_inhibition.name: substrate_inhibition}

               
        else:
            competitive_inhibition = KineticModel(
                name="competitive inhibition",
                params=["K_ic"],
                w0={"cS": substrate, "cE": enzyme,
                    "cP": product, "cI": inhibitor},            
                kcat_initial=self.initial_kcat,
                Km_initial=self.initial_Km,
                model=competitive_inhibition_model,
                enzyme_inactivation=self.enzyme_inactivation
            )
            uncompetitive_inhibition = KineticModel(
                name="uncompetitive inhibition",
                params=["K_iu"],
                w0={"cS": substrate, "cE": enzyme,
                    "cP": product, "cI": inhibitor},            
                kcat_initial=self.initial_kcat,
                Km_initial=self.initial_Km,
                model=uncompetitive_inhibition_model,
                enzyme_inactivation=self.enzyme_inactivation
            )
            noncompetitive_inhibition = KineticModel(
                name="non-competitive inhibition",
                params=["K_iu", "K_ic"],
                w0={"cS": substrate, "cE": enzyme,
                    "cP": product, "cI": inhibitor},
                kcat_initial=self.initial_kcat,
                Km_initial=self.initial_Km,
                model=noncompetitive_inhibition_model,
                enzyme_inactivation=self.enzyme_inactivation
            )
            partially_competitive_inhibition = KineticModel(
                name="partially competitive inhibition",
                params=["K_ic", "K_iu"],
                w0={"cS": substrate, "cE": enzyme,
                    "cP": product, "cI": inhibitor},            
                kcat_initial=self.initial_kcat,
                Km_initial=self.initial_Km,
                model=partially_competitive_inhibition_model,
                enzyme_inactivation=self.enzyme_inactivation
            )
            return {
                competitive_inhibition.name: competitive_inhibition,
                uncompetitive_inhibition.name: uncompetitive_inhibition,
                noncompetitive_inhibition.name: noncompetitive_inhibition,
                partially_competitive_inhibition.name: partially_competitive_inhibition,
            }

    def _run_minimization(self) -> None:

        print("Fitting data to:")
        for kineticmodel in self.models.values():
            print(f" - {kineticmodel.name} model")

            def g(time: np.ndarray, w0: tuple, params):
                '''
                Solution to the ODE w'(t)=f(t,w,p) with initial condition w(0)= w0 (= [S0])
                '''
                w = odeint(kineticmodel.model, w0, time, args=(params, self.enzyme_inactivation,))
                return w

            def residual(params, time: np.ndarray, substrate: np.ndarray):
                residuals = 0.0 * substrate
                for i, measurement in enumerate(substrate):

                # Calculate residual for each measurement
                    cS, cE, cP, cI = kineticmodel.w0.values()
                    w0 = (cS[i, 0], cE[i], cP[i, 0], cI[i, 0])

                    model = g(time, w0, params)  # solve the ODE with sfb.

                    # get modeled substrate
                    model = model[:, 0]

                    # compute distance to measured data
                    residuals[i] = measurement-model

                return residuals.flatten()

            kineticmodel.result = minimize(residual, kineticmodel.parameters, args=(
                self.subset_time, self.subset_substrate), method='leastsq', nan_policy='omit')
            

    def _result_overview(self):

        if np.all(self.inhibitor == 0):
            inhibitor_unit = self.data.data_conc_unit
        else:
            inhibitor_unit = self.data.measurements[0].inhibitor_conc_unit

        parameter_mapper = {
            "k_cat": f"kcat [1/{self.data.time_unit}]",
            "Km": f"Km [{self.data.data_conc_unit}]",
            "K_ic": f"Ki competitive [{inhibitor_unit}]",
            "K_iu": f"Ki uncompetitive [{inhibitor_unit}]",
            "K_ie": f"ki time-dep enzyme-inactiv. [1/{self.data.time_unit}]",
        }

        result_dict = {}
        for model in self.models.values():
            name = model.name
            aic = round(model.result.aic)

            parameter_dict = {}
            for parameter in model.result.params.values():
                name = parameter_mapper[parameter.name]
                value = parameter.value
                stderr = parameter.stderr

                try:
                    percentual_stderr = stderr / value * 100
                except TypeError:
                    percentual_stderr = float("nan")

                if name.startswith("Ki time-dep"):
                    parameter_dict[name] = f"{value:.5f} +/- {percentual_stderr:.2f}%"
                else:
                    parameter_dict[name] = f"{value:.5f} +/- {percentual_stderr:.2f}%"


            result_dict[model.name] = {"AIC": aic, **parameter_dict}

        df = DataFrame.from_dict(result_dict).T.sort_values("AIC", ascending=True)
        df.fillna('-', inplace=True)

        return df


    def fit_models(
        self,
        initial_substrate_concs: list = None,
        start_time_index: int = None,
        stop_time_index: int = None,
        enzyme_inactivation: bool = False,
        ):

        self.enzyme_inactivation = enzyme_inactivation

        # Subset data if one or multiple attributes are passed to the function
        if np.any([initial_substrate_concs, start_time_index, stop_time_index]):
            self.subset_substrate, self.subset_product, self.subset_enzyme, self.subset_initial_substrate, self.subset_time, self.subset_inhibitor = self._subset_data(
                initial_substrates=initial_substrate_concs,
                start_time_index=start_time_index,
                stop_time_index=stop_time_index)            
        else:
            self.subset_substrate = self.substrate
            self.subset_product = self.product
            self.subset_enzyme = self.enzyme
            self.subset_initial_substrate = self.initial_substrate
            self.subset_time = self.time
            self.subset_inhibitor = self.inhibitor


        # Initialize kinetics models
        self.models = self._initialize_models(
            substrate=self.subset_substrate,
            product=self.subset_product,
            enzyme=self.subset_enzyme,
            inhibitor=self.subset_inhibitor)

        self._run_minimization()

        self.result_dict = self._result_overview()
        display(self.result_dict)

    def _mean_w0(self, measurement_data: np.ndarray, init_substrate):
        unique = np.unique(init_substrate)
        mean_array = np.array([])
        for concentration in unique:
            idx = np.where(init_substrate == concentration)
            mean = np.mean(measurement_data[idx], axis=0)
            if mean_array.size == 0:
                mean_array = np.append(mean_array, mean)
            else:
                mean_array = np.vstack([mean_array, mean])
        return mean_array


    def visualize(
        self,
        model_name: Optional[str] = None,
        path: Optional[str] = None,
        title: Optional[str] = None,
        visualize_species: Optional[str] = None,
        plot_means: bool = False,
        **plt_kwargs):

        # Select which model to visualize
        best_model = self.result_dict.index[0]
        if model_name is None:
            model_name = best_model
        model = self.models[model_name]

        if plot_means:
            cS, cE, cP, cI = [self._mean_w0(data, self.subset_initial_substrate) for data in model.w0.values()]
        else:
            cS, cE, cP, cI = model.w0.values()

        # Visualization modes
        plot_modes = {
            "substrate": [self.subset_substrate,0, self.data.reactant_name], # Substrate
            "product": [self.subset_product, 2, self.data.reactant_name], # TODO Product
        }

        if visualize_species is None:
            if self.data.stoichiometry == StoichiometryTypes.SUBSTRATE:
                experimental_data, reactant, name = plot_modes["substrate"]
            else:
                experimental_data, reactant, name = plot_modes["product"]
        else:
            experimental_data, reactant, name = plot_modes[visualize_species]

        if plot_means:
            experimental_data, stddev = self._calculate_mean_std(data=experimental_data)

        def g(t, w0, params):

            '''
            Solution to the ODE w'(t)=f(t,w,p) with initial condition w(0)= w0 = cS
            '''

            w = odeint(model.model, w0, t, args=(params, self.enzyme_inactivation,))
            return w

        unique_a = np.unique(self.inhibitor)
        markers = ["o", "x", "D", "X", "d"]
        marker_mapping = dict(zip(unique_a, markers[:len(unique_a)]))
        marker_vector = [marker_mapping[item] for item in self.inhibitor[:,0]]

        unique_concs = np.unique(self.subset_initial_substrate)
        cmap = get_cmap("tab20").colors
        color_mapping = dict(zip(unique_concs, cmap[:len(unique_concs)]))
        if plot_means:
            color_vector = [color_mapping[item] for item in np.unique(self.subset_initial_substrate)]
        else:
            color_vector = [color_mapping[item] for item in self.subset_initial_substrate]

        for i, data in enumerate(experimental_data):

            w0 = (cS[i,0], cE[i], cP[i,0], cI[i,0])


            # Plot data
            if plot_means:
                ax = plt.errorbar(self.subset_time, data, stddev[i], label=np.unique(self.subset_initial_substrate)[i], fmt=marker_vector[i], color=color_vector[i], **plt_kwargs)
            else:
                ax = plt.scatter(x=self.subset_time, y=data, label=self.subset_initial_substrate[i], marker=marker_vector[i], color=color_vector[i], **plt_kwargs)

            data_fitted = g(t=self.subset_time, w0=w0, params=model.result.params)

            # Plot model
            ay = plt.plot(self.subset_time, data_fitted[:,reactant], color = color_vector[i])

        if title is None:
            plt.title(self.data.title)
        else:
            plt.title(title)

        plt.ylabel(f"{name} [{self.data.data_conc_unit}]")
        plt.xlabel(f"time [{self.data.time_unit}]")

        # Legend
        handles, labels = plt.gca().get_legend_handles_labels()

        new_handles, new_labels = [[],[]]
        for handle, label in zip(handles, labels):
            if len(new_labels) == 0:
                new_labels.append(label)
                new_handles.append(handle)
            else:
                if label == new_labels[-1]:
                    pass
                else:
                    new_labels.append(label)
                    new_handles.append(handle)

        plt.legend(title = f"initial substrate [{self.data.data_conc_unit}]", handles=new_handles, labels=new_labels, loc='center left', bbox_to_anchor=(1, 0.5))
        if path != None:
            plt.savefig(path, format="svg")
        plt.show()
        report_title = f"Fit report for {model.name} model"
        print(f"{len(report_title)}")
        report_fit(model.result)

    def _calculate_mean_std(self, data: np.ndarray):
        mean_data = np.array([])
        std_data = np.array([])
        unique_initial_substrates = np.unique(self.subset_initial_substrate)
        for concentration in unique_initial_substrates:
            idx = np.where(self.subset_initial_substrate == concentration)
            mean_data = np.append(mean_data, np.mean(data[idx], axis=0))
            std_data = np.append(std_data, np.std(data[idx], axis=0))

        mean_data = mean_data.reshape(len(unique_initial_substrates), int(len(mean_data)/len(unique_initial_substrates)))
        std_data = std_data.reshape(len(unique_initial_substrates), int(len(std_data)/len(unique_initial_substrates)))
        
        return mean_data, std_data

    

if __name__ == "__main__":
    from EnzymeKinetics.core.measurement import Measurement
    import matplotlib.pyplot as plt
    import numpy as np

    m1 = Measurement(
        initial_substrate_conc=100,
        enzyme_conc=0.05,
    )
    m1.add_to_data([0.0,1,2,3,4,5])
    m1.add_to_data([0.3,1.3,2.3,3.3,4.3,5.3])
    m1.add_to_data([0.6,1.6,2.6,3.6,4.6,5.6])

    m2 = Measurement(
    initial_substrate_conc=200,
    enzyme_conc=0.05,
    inhibitor_conc=0.0
    )
    m2.add_to_data([5,6,7,8,9,10])
    m2.add_to_data([5.3,6.3,7.3,8.3,9.3,10.3])
    m2.add_to_data([8.6,9.6,10.6,11.6,12.6,13.6])

    m3 = Measurement(
    initial_substrate_conc=300,
    enzyme_conc=0.11,
    )
    m3.add_to_data([10,11,15,20,25,30])
    m3.add_to_data([10.3,11.3,21.3,31.3,41.3,51.3])
    m3.add_to_data([10.6,11.6,15,31.6,41.6,71.6])

    testdata = EnzymeKineticsExperiment(
        data_conc_unit="mmole / l",
        stoichiometry="product",
        data_conc="mmole / l",
        time_unit="min",
        title="test data",
        reactant_name="test product",
        measurements=[m1,m2,m3],
        time=[0,2,4,6,8,9]
    )

    estimator = ParameterEstimator(data=testdata)
    estimator.fit_models(stop_time_index=-1)
    estimator.visualize(plot_means=True)
    #print(test.fit_models(initial_substrate_concs=[],start_time_index=4))

# TODO Typo


